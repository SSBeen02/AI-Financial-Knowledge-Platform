import babyLion from "@/data/Level_Character/Baby_Lion.png";
import braveLion from "@/data/Level_Character/Brave_Lion.png";
import jungleLion from "@/data/Level_Character/Jungle_Lion.png";
import type { StaticImageData } from "next/image";

export type LevelKey = "baby_lion" | "brave_lion" | "jungle_lion";

export interface LevelCharacter {
  key: LevelKey;
  name: string;
  image: StaticImageData;
  description: string;
}

const LEVELS: Record<LevelKey, Omit<LevelCharacter, "key">> = {
  baby_lion: {
    name: "아기 사자",
    image: babyLion,
    description: "금융 기초를 차근차근 쌓아가는 단계예요.",
  },
  brave_lion: {
    name: "용맹한 사자",
    image: braveLion,
    description: "기본기가 탄탄하고 더 깊은 학습을 준비하는 단계예요.",
  },
  jungle_lion: {
    name: "밀림의 왕",
    image: jungleLion,
    description: "폭넓은 금융 지식을 갖춘 상위 수준의 학습자예요.",
  },
};

export function getLevelFromScore(correctCount: number): LevelCharacter {
  if (correctCount <= 15) {
    return { key: "baby_lion", ...LEVELS.baby_lion };
  }
  if (correctCount <= 25) {
    return { key: "brave_lion", ...LEVELS.brave_lion };
  }
  return { key: "jungle_lion", ...LEVELS.jungle_lion };
}
