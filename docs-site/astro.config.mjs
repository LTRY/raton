import { readdirSync } from 'node:fs';
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { unified } from '@astrojs/markdown-remark';
import rehypeSpec from './plugins/rehype-spec.mjs';

// The sidebar is built from the spec folder because Starlight's autogenerate does not pick up the content root;
// labels come from each spec's frontmatter title. README.md is the home page (slug "index").
const specDir = new URL('../docs/spec/', import.meta.url);
const specItems = readdirSync(specDir)
  .filter((f) => f.endsWith('.md') && f !== 'README.md')
  .sort()
  .map((f) => ({ slug: f.slice(0, -3) }));

export default defineConfig({
  markdown: { processor: unified({ rehypePlugins: [rehypeSpec] }) },
  integrations: [
    starlight({
      title: 'Raton — spec',
      customCss: ['./src/styles/spec.css'],
      defaultLocale: 'root',
      locales: { root: { label: 'Français', lang: 'fr' } },
      sidebar: [{ label: 'Cahier des charges', items: [{ slug: 'index' }, ...specItems] }],
    }),
  ],
});
