import { restoreCache } from '@actions/cache';

for (const { path: directory, key } of JSON.parse(process.env.NATIVE_CACHES)) {
  const restored = await restoreCache([directory], key);
  if (restored !== key) throw new Error(`Required native build cache is missing: ${key}`);
}
