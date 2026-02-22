import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Toaster } from "sonner";
import "@/styles/globals.css";
import { AppSidebar } from "@/components/app-sidebar";
import { MobileWarning } from "@/components/mobile-warning";
import { ThemeProvider } from "@/components/theme-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { ThreadRefreshProvider } from "@/contexts/sidebar-context";
import { ToolDescriptionsProvider } from "@/contexts/tool-descriptions-context";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Anomaly Detection",
  description: "",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} antialiased`}>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <MobileWarning />
          <Toaster richColors position="bottom-left" />
          <ToolDescriptionsProvider>
            <ThreadRefreshProvider>
              <SidebarProvider>
                <AppSidebar />
                <SidebarInset>{children}</SidebarInset>
              </SidebarProvider>
            </ThreadRefreshProvider>
          </ToolDescriptionsProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
