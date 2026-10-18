import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

// docs/spec/ is the single source of the specs: read in place, never copied.
export const collections = {
  docs: defineCollection({ loader: glob({ pattern: '*.md', base: '../docs/spec' }), schema: docsSchema() }),
};
