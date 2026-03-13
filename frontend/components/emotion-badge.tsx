import { getEmotionClass } from "@/lib/store";

interface EmotionBadgeProps {
  emotion: string | null;
  confidence: number | null;
}

export function EmotionBadge({ emotion, confidence }: EmotionBadgeProps) {
  if (!emotion || emotion === "unknown") return null;

  return (
    <span
      className={`badge text-2xs ${getEmotionClass(emotion)}`}
      title={confidence ? `${(confidence * 100).toFixed(0)}% confidence` : undefined}
    >
      {emotion}
    </span>
  );
}
