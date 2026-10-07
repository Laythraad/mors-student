// /books is not an index: the shelf lives at /library (nav "المكتبة").
// Without this route the path 404'd — a dead link inside the app.
import { redirect } from "next/navigation";

export default function BooksIndexPage() {
  redirect("/library");
}
