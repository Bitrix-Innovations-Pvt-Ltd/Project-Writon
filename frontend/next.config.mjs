/** @type {import('next').NextConfig} */
const nextConfig = {
    output: "standalone",
    eslint: {
        // ESLint runs in CI (GitHub Actions), not during Docker builds
        ignoreDuringBuilds: true,
    },
    typescript: {
        // Type errors also caught in CI
        ignoreBuildErrors: true,
    },
};

export default nextConfig;
