"use server";

import { createClient } from "@/utils/supabase/server";
import { isSupabaseConfigured } from "@/lib/supabase-config";

export async function getStartDestination(): Promise<string> {
  if (!isSupabaseConfigured()) {
    return "/login";
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return "/login";
  }

  const { data } = await supabase
    .from("pre_test_results")
    .select("id")
    .eq("user_id", user.id)
    .limit(1)
    .maybeSingle();

  if (!data) {
    return "/pre-test";
  }

  return "/main";
}
