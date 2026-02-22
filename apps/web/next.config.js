import path from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

const workerAliases = {
  "@neo4j-nvl/layout-workers/lib/cosebilkent-layout/workerFactory.mjs":
    path.resolve(__dirname, "lib/nvl-workers/cose-worker-factory.mjs"),
  "@neo4j-nvl/layout-workers/lib/hierarchical-layout/workerFactory.mjs":
    path.resolve(__dirname, "lib/nvl-workers/hierarchical-worker-factory.mjs"),
};

/** @type {import('next').NextConfig} */
const nextConfig = {
  devIndicators: false,
  transpilePackages: ["@neo4j-nvl/react", "@neo4j-nvl/base"],
  turbopack: {
    resolveAlias: workerAliases,
  },
  webpack(config) {
    config.resolve.alias = {
      ...config.resolve.alias,
      ...workerAliases,
    };
    return config;
  },
};

export default nextConfig;
