import path from "node:path";

/** @type {import('next').NextConfig} */
const config = {
  outputFileTracingRoot: path.join(import.meta.dirname, "..", ".."),
};

export default config;
