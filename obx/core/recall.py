"""Recall orchestration: scoring, item selection, and session management."""

from typing import List, Optional, Tuple, Union
from dataclasses import dataclass
from datetime import datetime

from obx.core.flashcard import Flashcard, FlashcardAlgorithm, calculate_memory_score
from obx.core.exercise import Exercise, ExerciseSelector, calculate_exercise_score


@dataclass
class RecallSession:
    """Tracks the state of a recall session."""
    flashcards: List[Flashcard]
    exercises: List[Exercise]
    note_paths: List[str]  # Which notes the items came from
    
    # Session config
    flashcards_only: bool = False
    exercises_only: bool = False
    
    # Stats
    items_reviewed: int = 0
    correct_count: int = 0
    
    @property
    def total_items(self) -> int:
        if self.flashcards_only:
            return len(self.flashcards)
        if self.exercises_only:
            return len(self.exercises)
        return len(self.flashcards) + len(self.exercises)
    
    def get_memory_score(self) -> float:
        return calculate_memory_score(self.flashcards)
    
    def get_exercise_score(self) -> float:
        return calculate_exercise_score(self.exercises)


class TopicTypeEstimator:
    """
    Estimates whether a topic should favor memory (flashcards) or comprehension (exercises).
    
    Uses heuristics based on topic keywords:
    - Math, proofs, coding, algorithms -> exercises (comprehension)
    - History, vocabulary, facts, definitions -> flashcards (memory)
    """
    
    # Keywords indicating exercise-heavy topics
    EXERCISE_KEYWORDS = {
        'math', 'mathematics', 'algebra', 'calculus', 'geometry', 'statistics',
        'proof', 'proofs', 'theorem', 'lemma', 'corollary',
        'programming', 'coding', 'algorithm', 'algorithms', 'data structure',
        'physics', 'chemistry', 'engineering',
        'problem solving', 'exercise', 'exercises',
        'implementation', 'code', 'practice',
    }
    
    # Keywords indicating flashcard-heavy topics
    FLASHCARD_KEYWORDS = {
        'history', 'historical', 'date', 'dates', 'event', 'events',
        'vocabulary', 'vocab', 'word', 'words', 'definition', 'definitions',
        'fact', 'facts', 'memorize', 'memory',
        'language', 'languages', 'grammar',
        'terminology', 'terms', 'concepts',
        'people', 'names', 'places', 'geography',
    }
    
    @classmethod
    def estimate(cls, topic: str, note_content: str = "") -> float:
        """
        Estimate the ratio of exercises to flashcards.
        
        Returns a float 0-1 where:
        - 0.0 = all flashcards
        - 0.5 = balanced
        - 1.0 = all exercises
        """
        combined = (topic + " " + note_content).lower()
        
        exercise_score = sum(1 for kw in cls.EXERCISE_KEYWORDS if kw in combined)
        flashcard_score = sum(1 for kw in cls.FLASHCARD_KEYWORDS if kw in combined)
        
        total = exercise_score + flashcard_score
        if total == 0:
            return 0.5  # Default balanced
        
        return exercise_score / total
    
    @classmethod
    def get_preference_weights(cls, topic: str, note_content: str = "") -> Tuple[float, float]:
        """
        Get weights for flashcard vs exercise selection.
        
        Returns (flashcard_weight, exercise_weight) normalized to sum to 1.
        """
        exercise_ratio = cls.estimate(topic, note_content)
        flashcard_weight = 1 - exercise_ratio
        exercise_weight = exercise_ratio
        return flashcard_weight, exercise_weight


class RecallOrchestrator:
    """
    Orchestrates the selection of items during a recall session.
    
    Uses a hierarchical approach:
    1. Decide whether to present a flashcard or exercise
    2. Use the respective algorithm to select which one
    """
    
    @classmethod
    def select_next(
        cls,
        flashcards: List[Flashcard],
        exercises: List[Exercise],
        topic: str = "",
        flashcards_only: bool = False,
        exercises_only: bool = False,
    ) -> Optional[Union[Flashcard, Exercise]]:
        """
        Select the next item to present.
        
        Returns None if no items are due/available.
        """
        if flashcards_only:
            return cls._get_due_flashcard(flashcards)
        
        if exercises_only:
            return ExerciseSelector.get_next(exercises)
        
        # Get weights based on topic
        fc_weight, ex_weight = TopicTypeEstimator.get_preference_weights(topic)
        
        # Get due flashcards and incomplete exercises
        due_flashcard = cls._get_due_flashcard(flashcards)
        next_exercise = ExerciseSelector.get_next(exercises)
        
        if due_flashcard is None and next_exercise is None:
            return None
        
        if due_flashcard is None:
            return next_exercise
        
        if next_exercise is None:
            return due_flashcard
        
        # Both available - use priority scores
        fc_priority = cls._flashcard_priority(due_flashcard) * (1 + fc_weight)
        ex_priority = cls._exercise_priority(next_exercise) * (1 + ex_weight)
        
        if fc_priority >= ex_priority:
            return due_flashcard
        return next_exercise
    
    @classmethod
    def _get_due_flashcard(cls, flashcards: List[Flashcard]) -> Optional[Flashcard]:
        """Get the most urgent due flashcard using FSRS retrievability."""
        now = datetime.now()
        due = [c for c in flashcards if c.is_due(now)]
        
        if not due:
            return None
        
        # Sort by priority:
        # 1. New cards first (need introduction)
        # 2. Learning/relearning (short-term memory steps)
        # 3. Reviewing cards by lowest retrievability (most forgotten first)
        def priority_key(card: Flashcard):
            state_priority = {
                'new': 0,
                'learning': 1,
                'relearning': 2,
                'reviewing': 3,
            }
            # For reviewing cards, use retrievability (lower = more urgent)
            if card.state.value == 'reviewing':
                return (state_priority['reviewing'], card.retrievability)
            return (
                state_priority.get(card.state.value, 3),
                0.0,  # Learning/new cards treated equally within their tier
            )
        
        return min(due, key=priority_key)
    
    @classmethod
    def _flashcard_priority(cls, card: Flashcard) -> float:
        """Calculate priority score for a flashcard using FSRS (higher = more urgent)."""
        if card.state.value == 'new':
            return 12.0  # New cards highest priority
        if card.state.value == 'learning':
            return 10.0
        if card.state.value == 'relearning':
            return 8.0
        
        # For reviewing cards, use inverse retrievability (lower R = higher priority)
        # R ranges from 0-1, so (1-R)*5 + 3 gives us 3-8 priority range
        priority = (1 - card.retrievability) * 5 + 3
        return priority
    
    @classmethod
    def _exercise_priority(cls, ex: Exercise) -> float:
        """Calculate priority score for an exercise (higher = more urgent)."""
        grade_priority = {
            0: 10.0,  # Not attempted - highest priority
            1: 8.0,   # Incorrect
            2: 3.0,   # Partial
            3: 1.0,   # Correct (for reinforcement)
        }
        return grade_priority.get(ex.grade.value, 5.0)
    
    @classmethod
    def has_due_items(
        cls,
        flashcards: List[Flashcard],
        exercises: List[Exercise],
        flashcards_only: bool = False,
        exercises_only: bool = False,
    ) -> bool:
        """Check if there are any due items remaining."""
        if flashcards_only:
            return cls._get_due_flashcard(flashcards) is not None
        if exercises_only:
            return ExerciseSelector.get_next(exercises) is not None
        return (
            cls._get_due_flashcard(flashcards) is not None
            or ExerciseSelector.get_next(exercises) is not None
        )
    
    @classmethod
    def select_next_early(
        cls,
        flashcards: List[Flashcard],
        exercises: List[Exercise],
        topic: str = "",
        flashcards_only: bool = False,
        exercises_only: bool = False,
    ) -> Optional[Union[Flashcard, Exercise]]:
        """
        Select next item for EARLY review (when all due items are done).
        
        Prioritizes flashcards closest to their due date (soon-to-be-due first).
        """
        if flashcards_only:
            return cls._get_early_review_flashcard(flashcards)
        
        if exercises_only:
            # For exercises, return one that's already attempted for reinforcement
            correct_exercises = [e for e in exercises if e.grade.value >= 2]
            if correct_exercises:
                return min(correct_exercises, key=lambda e: e.attempts)
            return None
        
        # Get early review candidates
        early_flashcard = cls._get_early_review_flashcard(flashcards)
        
        if early_flashcard is None:
            return None
        
        return early_flashcard
    
    @classmethod
    def _get_early_review_flashcard(cls, flashcards: List[Flashcard]) -> Optional[Flashcard]:
        """
        Get the best flashcard for early review using FSRS retrievability.
        
        Prioritizes cards with lowest retrievability (closest to forgetting).
        This makes early review more effective - you review what you're about
        to forget anyway, rather than cards you still remember well.
        """
        now = datetime.now()
        
        # Get non-due reviewing cards
        not_due_reviewing = [
            c for c in flashcards 
            if not c.is_due(now) and c.state.value == 'reviewing'
        ]
        
        if not not_due_reviewing:
            return None
        
        # Sort by retrievability (lowest first = most likely to forget soon)
        # This is the key insight: early review is most useful for cards
        # that are just about to drop below your target retention
        return min(not_due_reviewing, key=lambda c: c.retrievability)
    
    @classmethod
    def get_session_items(
        cls,
        flashcards: List[Flashcard],
        exercises: List[Exercise],
        limit: int = 20,
        topic: str = "",
        flashcards_only: bool = False,
        exercises_only: bool = False,
    ) -> List[Union[Flashcard, Exercise]]:
        """
        Get a list of items for a study session.
        
        Returns items in recommended order.
        """
        items = []
        remaining_fc = flashcards.copy()
        remaining_ex = exercises.copy()
        
        for _ in range(limit):
            next_item = cls.select_next(
                remaining_fc,
                remaining_ex,
                topic=topic,
                flashcards_only=flashcards_only,
                exercises_only=exercises_only,
            )
            
            if next_item is None:
                break
            
            items.append(next_item)
            
            # Remove from pool
            if isinstance(next_item, Flashcard):
                remaining_fc = [c for c in remaining_fc if c.id != next_item.id]
            else:
                remaining_ex = [e for e in remaining_ex if e.id != next_item.id]
        
        return items
