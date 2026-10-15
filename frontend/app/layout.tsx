import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Spectral } from "next/font/google";
import "./globals.css";

/* Spectral carries the answer prose - it is read, not scanned.
   IBM Plex was drawn for engineering documentation, which is exactly what
   this is. Plex Mono is reserved for real identifiers. */
const spectral = Spectral({
  variable: "--font-spectral",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
});

const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "OrgMemory — Company Brain",
  description:
    "Ask questions about your engineering organisation and get evidence-backed answers from a FalkorDB knowledge graph.",
};

/**
 * Applied before first paint so a dark-theme user never sees a white flash.
 * Kept inline and tiny for exactly that reason.
 */
const THEME_SCRIPT = `try{var t=localStorage.getItem('orgmemory-theme');if(t==='dark'||(!t&&matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.dataset.theme='dark'}}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${spectral.variable} ${plexSans.variable} ${plexMono.variable} antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-full">{children}</body>
    </html>
  );
}