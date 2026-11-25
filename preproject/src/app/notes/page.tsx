import { redirect } from "next/navigation";
import NotesClient from "@/components/notes/NotesClient";
import type { ExploreNoteListItem } from "@/lib/notes/types";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import { createClient } from "@/utils/supabase/server";

export const metadata = {
  title: "학습노트 | FinEdu",
};

export default async function NotesPage() {
  if (!isSupabaseConfigured()) {
    redirect("/login?next=/notes");
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login?next=/notes");
  }

  const { data } = await supabase
    .from("explore_notes")
    .select(
      "id, title, keywords, correct_count, total_quiz_count, has_wrong_answers, created_at"
    )
    .eq("user_id", user.id)
    .order("created_at", { ascending: false });

  const initialNotes = (data ?? []) as ExploreNoteListItem[];

  return (
    <div className="section-container py-10">
      <NotesClient initialNotes={initialNotes} />
    </div>
  );
}
