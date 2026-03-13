/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  headers: async () => [
    {
      source: '/sw.js',
      headers: [
        { key: 'Cache-Control', value: 'no-cache, no-store, must-revalidate' },
        { key: 'Service-Worker-Allowed', value: '/' },
      ],
    },
  ],
  skipTrailingSlashRedirect: true,
  rewrites: async () => ({
    beforeFiles: [
      {
        source: '/api/',
        destination: `${process.env.API_INTERNAL_URL || 'http://backend:8000'}/api/`,
      },
      {
        source: '/api/:path*/',
        destination: `${process.env.API_INTERNAL_URL || 'http://backend:8000'}/api/:path*/`,
      },
      {
        source: '/api/:path*',
        destination: `${process.env.API_INTERNAL_URL || 'http://backend:8000'}/api/:path*`,
      },
    ],
    afterFiles: [],
    fallback: [],
  }),
};

export default nextConfig;
