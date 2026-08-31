import type { Metadata } from "next";
import "./globals.css";
import QueryProvider from "./QueryProvider";

export const metadata: Metadata = {
  title: "Scarlet Composer",
  description: "Operator UI for Scarlets deployments",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
