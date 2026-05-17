import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const geistSans = Geist({
	variable: "--font-geist-sans",
	subsets: ["latin"],
});

const geistMono = Geist_Mono({
	variable: "--font-geist-mono",
	subsets: ["latin"],
});

// Brand wordmark font — Instrument Serif italic per Tecxmate Design System.
const brandScript = Instrument_Serif({
	variable: "--font-brand-script",
	subsets: ["latin"],
	weight: ["400"],
	style: ["italic"],
});

export const metadata: Metadata = {
	title: "tecxstock",
	description: "AI-driven research terminal for Taiwan equities (TWSE / TPEx).",
	icons: {
		icon: "/icon.svg",
		shortcut: "/icon.svg",
	},
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="en">
			<body
				className={`${geistSans.variable} ${geistMono.variable} ${brandScript.variable} antialiased`}
			>
				<TooltipProvider>{children}</TooltipProvider>
			</body>
		</html>
	);
}
