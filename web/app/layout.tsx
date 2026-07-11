import type { Metadata } from "next";
import { B612, B612_Mono, Michroma } from "next/font/google";
import { AuthRoot } from "@/components/auth/auth-root";
import { Providers } from "@/components/providers";
import "./globals.css";

// Space-age field manual: Michroma for display lettering, B612 (the Airbus
// cockpit face) for everything readable, B612 Mono for numeric readouts.
const michroma = Michroma({
  variable: "--font-michroma",
  weight: "400",
  subsets: ["latin"],
});

const b612 = B612({
  variable: "--font-b612",
  weight: ["400", "700"],
  style: ["normal", "italic"],
  subsets: ["latin"],
});

const b612Mono = B612_Mono({
  variable: "--font-b612-mono",
  weight: ["400", "700"],
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "crate",
  description: "Playlist intelligence for a personal Spotify library",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${michroma.variable} ${b612.variable} ${b612Mono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <AuthRoot>
          <Providers>{children}</Providers>
        </AuthRoot>
      </body>
    </html>
  );
}
