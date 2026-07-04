import "./globals.css";

export const metadata = {
  title: "Agent Control Center",
  description: "Live tracking for the resource-constrained agent",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
