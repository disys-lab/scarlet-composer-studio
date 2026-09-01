import { Card, CardContent } from "@/components/ui/card";

export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{title}</h1>
      <Card>
        <CardContent className="py-12 text-center text-sm text-gray-400">
          This page is coming in a follow-up pass.
        </CardContent>
      </Card>
    </div>
  );
}
