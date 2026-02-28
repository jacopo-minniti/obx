"""Exercise model with linear progression tracking."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Optional, List, Dict, Any


class ExerciseGrade(IntEnum):
    """Grade for an exercise attempt."""
    NOT_ATTEMPTED = 0
    INCORRECT = 1
    PARTIAL = 2
    CORRECT = 3


@dataclass
class Exercise:
    """
    An exercise with linear progression tracking.
    
    Unlike flashcards which use SRS, exercises follow linear progression:
    - Must achieve grade >= 2 to "complete" and progress
    - Ordered by difficulty and dependency
    """
    prompt: str
    hints: List[str] = field(default_factory=list)
    difficulty: str = "medium"  # easy, medium, hard
    order: int = 0  # Position in the note's exercise sequence
    
    # State
    grade: ExerciseGrade = ExerciseGrade.NOT_ATTEMPTED
    attempts: int = 0
    last_attempt: Optional[datetime] = None
    chat_history: List[Dict[str, str]] = field(default_factory=list) # List of {"role": "user/assistant", "content": "..."}
    
    # Unique identifier
    id: Optional[str] = None
    
    # Tags for filtering
    tags: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Generate ID if not provided."""
        if self.id is None:
            self.id = f"ex{hash(self.prompt) % 100000}"
    
    def is_complete(self) -> bool:
        """Check if the exercise is considered complete (grade >= PARTIAL)."""
        return self.grade >= ExerciseGrade.PARTIAL
    
    def is_correct(self) -> bool:
        """Check if the exercise was solved correctly."""
        return self.grade == ExerciseGrade.CORRECT
    
    def can_progress(self) -> bool:
        """Check if the user can move to the next exercise."""
        return self.grade >= ExerciseGrade.PARTIAL
    
    def record_attempt(self, grade: ExerciseGrade, feedback: Optional[str] = None) -> None:
        """Record an attempt on this exercise."""
        self.grade = grade
        self.attempts += 1
        self.last_attempt = datetime.now()
        if feedback:
            self.chat_history.append({"role": "assistant", "content": feedback})
    
    def add_chat_message(self, role: str, content: str) -> None:
        """Add a message to the chat history."""
        self.chat_history.append({"role": role, "content": content})
    
    def to_state_dict(self) -> Dict[str, Any]:
        """Serialize state to a dict for embedding in markdown."""
        return {
            "id": self.id,
            "grade": self.grade.value,
            "order": self.order,
            "difficulty": self.difficulty,
            "attempts": self.attempts,
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
        }
    
    @classmethod
    def from_state_dict(cls, prompt: str, state_dict: Dict[str, Any], hints: List[str] = None, tags: List[str] = None, chat_history: List[Dict[str, str]] = None) -> "Exercise":
        """Create an exercise from parsed state dict."""
        last_attempt = None
        if state_dict.get("last_attempt"):
            last_attempt = datetime.fromisoformat(state_dict["last_attempt"])
        
        return cls(
            prompt=prompt,
            hints=hints or [],
            difficulty=state_dict.get("difficulty", "medium"),
            order=state_dict.get("order", 0),
            grade=ExerciseGrade(state_dict.get("grade", 0)),
            attempts=state_dict.get("attempts", 0),
            last_attempt=last_attempt,
            id=state_dict.get("id"),
            tags=tags or [],
            chat_history=chat_history or [],
        )


class ExerciseSelector:
    """
    Selects the next exercise to present based on linear progression.
    
    Priority:
    1. Incomplete exercises (grade < 2) in order
    2. Exercises that need improvement (grade == 2)
    3. If all correct, cycle through for reinforcement
    """
    
    @classmethod
    def get_next(cls, exercises: List[Exercise]) -> Optional[Exercise]:
        """Get the next exercise to present."""
        if not exercises:
            return None
        
        # Sort by order first
        sorted_exercises = sorted(exercises, key=lambda e: e.order)
        
        # Priority 1: First incomplete exercise (grade < 2)
        for ex in sorted_exercises:
            if ex.grade < ExerciseGrade.PARTIAL:
                return ex
        
        # Priority 2: First partial exercise (grade == 2)
        for ex in sorted_exercises:
            if ex.grade == ExerciseGrade.PARTIAL:
                return ex
        
        # All correct - return the one with fewest attempts for reinforcement
        return min(sorted_exercises, key=lambda e: e.attempts)
    
    @classmethod
    def get_incomplete(cls, exercises: List[Exercise]) -> List[Exercise]:
        """Get all incomplete exercises in order."""
        return [e for e in sorted(exercises, key=lambda e: e.order) if not e.is_complete()]
    
    @classmethod
    def get_for_session(cls, exercises: List[Exercise], limit: int = 5) -> List[Exercise]:
        """Get exercises for a study session."""
        incomplete = cls.get_incomplete(exercises)
        if incomplete:
            return incomplete[:limit]
        
        # All complete - return lowest scoring ones for review
        sorted_by_grade = sorted(exercises, key=lambda e: (e.grade.value, -e.attempts))
        return sorted_by_grade[:limit]


def calculate_exercise_score(exercises: List[Exercise]) -> float:
    """
    Calculate overall exercise score (0-1) based on grades.
    
    - CORRECT (3) = 1.0
    - PARTIAL (2) = 0.66
    - INCORRECT (1) = 0.33
    - NOT_ATTEMPTED (0) = 0.0
    """
    if not exercises:
        return 0.0
    
    total_score = 0.0
    for ex in exercises:
        total_score += ex.grade.value / 3.0
    
    return round(total_score / len(exercises), 2)
