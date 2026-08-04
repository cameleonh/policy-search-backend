import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Policy Search",
  description: "Unified youth and small-business policy search platform",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
