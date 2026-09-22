import { redirect } from "next/navigation";
import PreTestQuiz from "@/components/pre-test/PreTestQuiz";
import { generatePreTestQuestions } from "@/lib/pretest/select-questions";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import { createClient } from "@/utils/supabase/server";

export const metadata = {
  title: "사전테스트 | FinEdu",
  description: "금융 지식 수준을 파악하는 사전테스트",
};

export default async function PreTestPage() {
  if (!isSupabaseConfigured()) {
    redirect("/login?next=/pre-test");
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login?next=/pre-test");
  }

  const questions = generatePreTestQuestions();

  return <PreTestQuiz initialQuestions={questions} />;
}
