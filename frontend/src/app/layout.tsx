import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Providers from "./providers";
import NavMenu from "@/components/NavMenu";
import Header from "@/components/Header";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ARIV Recovery Engine",
  description: "Revenue operations control plane for autonomous payment recovery.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-slate-50 text-slate-900 min-h-screen flex antialiased`}>
        <Providers>
          <NavMenu />
          <div className="flex flex-col flex-1 min-w-0">
            <Header />
            <main className="flex-1 p-6 min-h-0">
              {children}
            </main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
