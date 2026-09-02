import type { NextConfig } from "next";

const backendOrigin = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/web/:path*",
        destination: `${backendOrigin}/web/:path*`,
      },
      {
        source: "/oauth/:path*",
        destination: `${backendOrigin}/oauth/:path*`,
      },
    ];
  },
};

export default nextConfig;
