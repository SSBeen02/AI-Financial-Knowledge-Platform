import { isSupabaseConfigured } from "@/lib/supabase-config";
import { getSafeUser } from "@/lib/supabase-safe";
import { createClient } from "@/utils/supabase/server";

export async function hasCompletedPreTest(userId?: string): Promise<boolean> {
  if (!isSupabaseConfigured() || !userId) {
    return false;
  }

  try {
    const supabase = await createClient();
    const { data } = await supabase
      .from("pre_test_results")
      .select("id")
      .eq("user_id", userId)
      .limit(1)
      .maybeSingle();

    return Boolean(data);
  } catch {
    return false;
  }
}

export async function getLatestPreTestScore(
  userId: string
): Promise<number | null> {
  if (!isSupabaseConfigured()) {
    return null;
  }

  try {
    const supabase = await createClient();
    const { data } = await supabase
      .from("pre_test_results")
      .select("total_score")
      .eq("user_id", userId)
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle();

    return data?.total_score ?? null;
  } catch {
    return null;
  }
}

export async function getHeaderNavState() {
  if (!isSupabaseConfigured()) {
    return { showPreTest: true, isLoggedIn: false };
  }

  const user = await getSafeUser();

  if (!user) {
    return { showPreTest: true, isLoggedIn: false };
  }

  const completed = await hasCompletedPreTest(user.id);
  return { showPreTest: !completed, isLoggedIn: true };
}
