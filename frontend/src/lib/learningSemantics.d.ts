import type { LearningExampleCategory } from "./api";

export type LearningPracticeAnswer = "call" | "put" | "wait" | "reject";

export function expectedLearningAnswers(
  category: LearningExampleCategory,
  direction: string,
): LearningPracticeAnswer[];

export function scoreLearningAnswer(
  category: LearningExampleCategory,
  direction: string,
  answer: LearningPracticeAnswer,
): boolean;
