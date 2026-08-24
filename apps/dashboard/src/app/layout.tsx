import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';
import { Providers } from './providers';
import { Toaster } from '@/components/ui/toaster';
import { SITE_URL } from '@/lib/site';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: 'WebChat AI — AI chatbots grounded in your website content',
    template: '%s | WebChat AI',
  },
  description:
    'Multi-tenant AI SaaS platform. Create a website-specific AI assistant in minutes with zero code.',
  keywords: [
    'website AI chatbot',
    'RAG chatbot',
    'knowledge base assistant',
    'embeddable chat widget',
  ],
  alternates: {
    canonical: '/',
  },
  openGraph: {
    type: 'website',
    siteName: 'WebChat AI',
    url: '/',
    title: 'WebChat AI — AI chatbots grounded in your website content',
    description:
      'Add your website, let the AI learn your content, and embed a RAG-powered chat widget with one script tag.',
  },
  twitter: {
    card: 'summary',
    title: 'WebChat AI — AI chatbots grounded in your website content',
    description:
      'Add your website, let the AI learn your content, and embed a RAG-powered chat widget with one script tag.',
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <Providers>{children}</Providers>
        <Toaster />
      </body>
    </html>
  );
}
