import type { NextConfig } from "next";
import { securityHeaders } from "./lib/security-headers";

const config: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders(process.env.NODE_ENV !== "production") }];
  },
};

export default config;
