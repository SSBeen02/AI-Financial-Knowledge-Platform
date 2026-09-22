import { redirect } from "next/navigation";
import ExploreChat from "@/components/explore/ExploreChat";
import { getLatestPreTestScore } from "@/lib/pre-test-status";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import { createClient } from "@/utils/supabase/server";

export const metadata = {
  title: "금융지식 탐색하기 | FinEdu",
};

export default async function ExplorePage() {
  let preTestScore: number | null = null;

  if (isSupabaseConfigured()) {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (!user) {
      redirect("/login?next=/explore");
    }

    preTestScore = await getLatestPreTestScore(user.id);
  }

  return (
    <div className="section-container py-6 sm:py-8">
      <ExploreChat preTestScore={preTestScore} />
    </div>
  );
}
