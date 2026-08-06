/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `next build` and `next dev` share .next/ by default, so building while a
  // dev server is running overwrites the exact chunks that server is mid-way
  // through serving. Every route then 500s with `Cannot find module
  // './819.js'` — a message that points at webpack internals and says nothing
  // about the actual cause, and survives a page reload, so it reads like the
  // app is broken rather than the build directory.
  //
  // Defaults to .next, so deploy/ and scripts/ are unaffected. Set
  // NEXT_DIST_DIR to build somewhere else while dev keeps running:
  //     NEXT_DIST_DIR=.next-build npm run build
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
