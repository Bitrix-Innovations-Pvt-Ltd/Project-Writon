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
    async rewrites() {
        return [
            {
                source: '/api/:path*',
                destination: process.env.NEXT_PUBLIC_API_URL 
                    ? `${process.env.NEXT_PUBLIC_API_URL}/api/:path*` 
                    : 'http://127.0.0.1:8000/api/:path*' // Proxy to backend
            }
        ];
    }
};

export default nextConfig;
