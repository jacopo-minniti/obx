"""Flashcard model with FSRS (Free Spaced Repetition Scheduler) algorithm."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Tuple, Dict, Any
import math
import uuid


class FlashcardState(str, Enum):
    """State of a flashcard in the SRS system."""
    NEW = "new"
    LEARNING = "learning"
    REVIEWING = "reviewing"
    RELEARNING = "relearning"


class Rating(str, Enum):
    """User rating for a flashcard review."""
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"
    
    def to_int(self) -> int:
        """Convert rating to FSRS integer (1-4)."""
        return {
            Rating.AGAIN: 1,
            Rating.HARD: 2,
            Rating.GOOD: 3,
            Rating.EASY: 4
        }[self]


@dataclass
class Flashcard:
    """
    A flashcard with FSRS state.
    
    Uses Stability (S) and Difficulty (D) instead of ease factor.
    Stability = days until retrievability drops to target (usually 90%).
    Difficulty = how hard the card is (1-10 scale).
    """
    question: str
    answer: str
    tags: List[str] = field(default_factory=list)
    
    # SRS State
    state: FlashcardState = FlashcardState.NEW
    step: int = 0
    due_date: Optional[datetime] = None
    last_reviewed: Optional[datetime] = None
    
    # FSRS specific fields
    stability: float = 0.0      # Memory stability in days
    difficulty: float = 5.0     # Card difficulty (1-10)
    scheduled_days: int = 0     # Actual interval given
    
    # Unique identifier
    id: Optional[str] = None
    
    def __post_init__(self):
        """Generate stable ID if not provided."""
        if self.id is None:
            self.id = uuid.uuid4().hex[:8]
    
    @property
    def retrievability(self) -> float:
        """
        Calculate current probability of recall (R) based on time elapsed.
        
        Formula: R = (1 + elapsed / (9 * S)) ^ -1
        Where S is stability.
        """
        if self.state == FlashcardState.NEW or self.last_reviewed is None:
            return 0.0
        
        elapsed_days = (datetime.now() - self.last_reviewed).total_seconds() / 86400
        if self.stability <= 0:
            return 0.0
            
        return (1 + elapsed_days / (9 * self.stability)) ** -1

    def is_due(self, now: Optional[datetime] = None) -> bool:
        """Check if this flashcard is due for review."""
        if now is None:
            now = datetime.now()
        if self.due_date is None:
            return True  # New cards are always due
        return now >= self.due_date
    
    def time_until_due(self, now: Optional[datetime] = None) -> Optional[timedelta]:
        """Get time remaining until card is due (for early review ranking)."""
        if now is None:
            now = datetime.now()
        if self.due_date is None:
            return None
        return self.due_date - now
    
    def to_state_dict(self) -> Dict[str, Any]:
        """Serialize SRS state to a dict for embedding in markdown."""
        return {
            "id": self.id,
            "state": self.state.value,
            "step": self.step,
            "S": round(self.stability, 2),       # Stability
            "D": round(self.difficulty, 2),       # Difficulty
            "days": self.scheduled_days,
            "due": self.due_date.isoformat() if self.due_date else None,
            "reviewed": self.last_reviewed.isoformat() if self.last_reviewed else None,
        }
    
    @classmethod
    def from_state_dict(
        cls, 
        question: str, 
        answer: str, 
        state_dict: Dict[str, Any], 
        tags: List[str] = None
    ) -> "Flashcard":
        """Create a flashcard from parsed state dict."""
        due_date = None
        if state_dict.get("due"):
            due_date = datetime.fromisoformat(state_dict["due"])
        
        last_reviewed = None
        if state_dict.get("reviewed"):
            last_reviewed = datetime.fromisoformat(state_dict["reviewed"])
        
        # Handle both old format (ease/interval) and new format (S/D)
        # For fresh start, we only care about new format
        stability = state_dict.get("S", state_dict.get("stability", 0.0))
        difficulty = state_dict.get("D", state_dict.get("difficulty", 5.0))
        
        # Map old states to new
        state_value = state_dict.get("state", "new")
        if state_value == "learning" and stability == 0:
            state_value = "new"
        
        return cls(
            question=question,
            answer=answer,
            tags=tags or [],
            state=FlashcardState(state_value),
            step=state_dict.get("step", 0),
            stability=stability,
            difficulty=difficulty,
            scheduled_days=state_dict.get("days", state_dict.get("scheduled_days", 0)),
            due_date=due_date,
            last_reviewed=last_reviewed,
            id=state_dict.get("id"),
        )


class FlashcardAlgorithm:
    """
    FSRS (Free Spaced Repetition Scheduler) v4.5 Implementation.
    
    Key concepts:
    - Stability (S): How long until retrievability drops to target retention
    - Difficulty (D): How hard the card is (1-10)
    - Retrievability (R): Current probability of recall
    
    The algorithm uses 17 optimized weights to calculate intervals.
    """
    
    # Default FSRS Weights (v4.5) - optimized for general learning
    W = [
        0.40255, 1.18385, 3.173, 15.69105,   # W[0-3]: Initial stability by rating
        7.19605,                              # W[4]: Initial difficulty
        0.5345,                               # W[5]: Difficulty mean reversion
        1.4604,                               # W[6]: Difficulty update rate
        0.0046,                               # W[7]: (unused in v4.5)
        1.54575,                              # W[8]: Stability increase base
        0.1192,                               # W[9]: Stability increase power
        1.01925,                              # W[10]: Retrievability factor
        1.9395,                               # W[11]: Failure penalty base
        0.11,                                 # W[12]: Difficulty factor for failure
        0.29605,                              # W[13]: Stability factor for failure
        2.2698,                               # W[14]: Retrievability factor for failure
        0.2315,                               # W[15]: Easy bonus
        2.9482                                # W[16]: (unused in v4.5)
    ]
    
    # Configuration
    REQUEST_RETENTION = 0.9   # Target retention (90%)
    MAX_INTERVAL = 36500      # Max interval days (~100 years)
    
    # Learning steps before graduating to FSRS
    LEARNING_STEPS = [timedelta(minutes=1), timedelta(minutes=10)]
    RELEARNING_STEPS = [timedelta(minutes=10)]

    @classmethod
    def get_options(cls, card: Flashcard) -> List[Tuple[Rating, Flashcard]]:
        """
        Get all possible next states for a card based on all ratings.
        
        Returns list of (rating, new_card_state) tuples.
        """
        now = datetime.now()
        return [
            (Rating.AGAIN, cls._next_card(card, Rating.AGAIN, now)),
            (Rating.HARD, cls._next_card(card, Rating.HARD, now)),
            (Rating.GOOD, cls._next_card(card, Rating.GOOD, now)),
            (Rating.EASY, cls._next_card(card, Rating.EASY, now)),
        ]

    @classmethod
    def apply_rating(cls, card: Flashcard, rating: Rating) -> Flashcard:
        """Apply a rating to a card and return the updated card."""
        return cls._next_card(card, rating, datetime.now())

    @classmethod
    def _next_card(cls, card: Flashcard, rating: Rating, now: datetime) -> Flashcard:
        """
        Compute the next state of the card for a specific rating.
        
        Handles transitions between states and applies FSRS formulas.
        Early reviews are handled gracefully - the retrievability calculation
        naturally accounts for elapsed time.
        """
        new_card = Flashcard(
            question=card.question,
            answer=card.answer,
            tags=card.tags,
            state=card.state,
            step=card.step,
            stability=card.stability,
            difficulty=card.difficulty,
            scheduled_days=card.scheduled_days,
            due_date=card.due_date,
            last_reviewed=now,
            id=card.id
        )

        # === NEW CARD ===
        if new_card.state == FlashcardState.NEW:
            cls._init_ds(new_card, rating)
            new_card.state = FlashcardState.LEARNING
            new_card.step = 0
            
            if rating == Rating.EASY:
                # Easy immediately graduates to Reviewing
                new_card.state = FlashcardState.REVIEWING
                interval = cls._next_interval(new_card.stability)
                new_card.scheduled_days = interval
                new_card.due_date = now + timedelta(days=interval)
            else:
                new_card.due_date = now + cls.LEARNING_STEPS[0]
            
            return new_card

        # === LEARNING STATE ===
        elif new_card.state == FlashcardState.LEARNING:
            if rating == Rating.AGAIN:
                new_card.step = 0
                new_card.due_date = now + cls.LEARNING_STEPS[0]
                cls._init_ds(new_card, rating)
                
            elif rating == Rating.HARD:
                # Stay in current step
                step_idx = min(new_card.step, len(cls.LEARNING_STEPS) - 1)
                new_card.due_date = now + cls.LEARNING_STEPS[step_idx]
                
            elif rating == Rating.GOOD:
                new_card.step += 1
                if new_card.step >= len(cls.LEARNING_STEPS):
                    # Graduate to Reviewing
                    new_card.state = FlashcardState.REVIEWING
                    cls._init_ds(new_card, rating)
                    interval = cls._next_interval(new_card.stability)
                    new_card.scheduled_days = interval
                    new_card.due_date = now + timedelta(days=interval)
                else:
                    new_card.due_date = now + cls.LEARNING_STEPS[new_card.step]
                    
            elif rating == Rating.EASY:
                # Graduate immediately with higher stability
                new_card.state = FlashcardState.REVIEWING
                cls._init_ds(new_card, rating)
                interval = cls._next_interval(new_card.stability)
                new_card.scheduled_days = interval
                new_card.due_date = now + timedelta(days=interval)
            
            return new_card

        # === RELEARNING STATE ===
        elif new_card.state == FlashcardState.RELEARNING:
            if rating == Rating.AGAIN:
                new_card.step = 0
                new_card.due_date = now + cls.RELEARNING_STEPS[0]
                
            elif rating == Rating.HARD:
                step_idx = min(new_card.step, len(cls.RELEARNING_STEPS) - 1)
                new_card.due_date = now + cls.RELEARNING_STEPS[step_idx]
                
            elif rating in [Rating.GOOD, Rating.EASY]:
                # Graduate back to Reviewing
                new_card.state = FlashcardState.REVIEWING
                interval = cls._next_interval(new_card.stability)
                if rating == Rating.EASY:
                    interval = max(interval, new_card.scheduled_days + 1)
                new_card.scheduled_days = interval
                new_card.due_date = now + timedelta(days=interval)
            
            return new_card

        # === REVIEWING STATE (main FSRS logic) ===
        elif new_card.state == FlashcardState.REVIEWING:
            # Calculate elapsed time and retrievability
            elapsed_days = 0.0
            if card.last_reviewed:
                elapsed_days = max(0, (now - card.last_reviewed).total_seconds() / 86400)
            
            # Current retrievability (accounts for early/late reviews naturally)
            if card.stability > 0:
                retrievability = (1 + elapsed_days / (9 * card.stability)) ** -1
            else:
                retrievability = 0.0
            
            # Update Difficulty (D)
            # Mean reversion towards W[4] with update based on rating
            next_d = card.difficulty - cls.W[6] * (rating.to_int() - 3)
            next_d = cls.W[5] * cls.W[4] + (1 - cls.W[5]) * next_d
            next_d = max(1.0, min(10.0, next_d))  # Clamp to 1-10
            
            # Update Stability (S) based on rating
            next_s = card.stability
            
            if rating == Rating.AGAIN:
                # Forgot - go to relearning
                new_card.state = FlashcardState.RELEARNING
                new_card.step = 0
                
                # Penalty for difficulty
                next_d = min(10.0, card.difficulty + cls.W[6])
                
                # Stability decrease formula
                next_s = (
                    cls.W[11] 
                    * (next_d ** -cls.W[12]) 
                    * ((card.stability + 1) ** cls.W[13]) 
                    * math.exp(cls.W[14] * (1 - retrievability))
                )
                next_s = max(0.1, next_s)
                
                new_card.stability = next_s
                new_card.difficulty = next_d
                new_card.due_date = now + cls.RELEARNING_STEPS[0]
                new_card.scheduled_days = 0
                return new_card
            
            # Successful review (Hard, Good, Easy)
            # Stability increase formula
            stability_increase = (
                math.exp(cls.W[8]) 
                * (11 - next_d) 
                * (card.stability ** -cls.W[9]) 
                * (math.exp(cls.W[10] * (1 - retrievability)) - 1)
            )
            
            if rating == Rating.HARD:
                # Hard: smaller stability increase
                next_s = card.stability * (1 + stability_increase * 0.5)
            elif rating == Rating.GOOD:
                # Good: normal stability increase
                next_s = card.stability * (1 + stability_increase)
            elif rating == Rating.EASY:
                # Easy: larger stability increase
                next_s = card.stability * (1 + stability_increase * cls.W[15])
            
            next_s = max(0.1, next_s)
            new_card.stability = next_s
            new_card.difficulty = next_d
            
            # Calculate next interval
            interval = cls._next_interval(next_s)
            
            # Ensure interval increases (or stays same for Hard)
            if rating == Rating.HARD:
                interval = max(card.scheduled_days, interval)
            else:
                interval = max(card.scheduled_days + 1, interval)
            
            new_card.scheduled_days = interval
            new_card.due_date = now + timedelta(days=interval)
            
            return new_card

        return new_card

    @classmethod
    def _init_ds(cls, card: Flashcard, rating: Rating):
        """Initialize Difficulty and Stability for new/reset cards."""
        r = rating.to_int()  # 1-4
        
        # Initial Stability based on first rating
        card.stability = cls.W[r - 1]
        
        # Initial Difficulty (centered around W[4], adjusted by rating)
        card.difficulty = cls.W[4] - (r - 3) * cls.W[5]
        card.difficulty = max(1.0, min(10.0, card.difficulty))

    @classmethod
    def _next_interval(cls, stability: float) -> int:
        """
        Calculate next interval in days for target retention.
        
        Formula: Interval = S * 9 * (1/R - 1)
        Where R is target retention (e.g., 0.9 for 90%)
        """
        new_interval = stability * 9 * (1 / cls.REQUEST_RETENTION - 1)
        return max(1, min(cls.MAX_INTERVAL, round(new_interval)))


def calculate_memory_score(cards: List[Flashcard]) -> float:
    """
    Calculate overall memory score (0-1) based on flashcard states.
    
    Uses retrievability for reviewing cards, step progress for learning.
    """
    if not cards:
        return 0.0
    
    total_score = 0.0
    
    for card in cards:
        if card.state == FlashcardState.NEW:
            card_score = 0.0
        elif card.state == FlashcardState.REVIEWING:
            # Use current retrievability
            card_score = card.retrievability
        elif card.state == FlashcardState.LEARNING:
            # Based on learning step progress
            max_steps = len(FlashcardAlgorithm.LEARNING_STEPS)
            card_score = 0.1 + (card.step / max_steps) * 0.3
        else:  # RELEARNING
            card_score = 0.2
        
        total_score += card_score
    
    return round(total_score / len(cards), 2)
