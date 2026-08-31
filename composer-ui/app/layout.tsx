import type { Metadata } from "next";
import "./globals.css";
import QueryProvider from "./QueryProvider";
import { AuthProvider } from "@/lib/context/AuthContext";

export const metadata: Metadata = {
  title: "Scarlet Composer",
  description: "Operator UI for Scarlets deployments",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <QueryProvider>
          <AuthProvider>{children}</AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
