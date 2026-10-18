// The specs are plain GitHub markdown read in place by Starlight, so two things are fixed up at render time:
// links between files ("11-interface-html.md#accueil") become site URLs, and the leading "# Title" line is
// dropped because Starlight already renders the frontmatter title as the page heading.
const SPEC_LINK = /^([\w.-]+)\.md(#.*)?$/;

export function rewriteHref(href) {
  const match = SPEC_LINK.exec(href);
  if (!match) return href;
  const [, name, hash = ''] = match;
  return (name === 'README' ? '/' : `/${name}/`) + hash;
}

export default function rehypeSpec() {
  return (tree) => {
    let h1Dropped = false;
    const walk = (node) => {
      if (!node.children) return;
      node.children = node.children.filter((child) => {
        if (!h1Dropped && child.type === 'element' && child.tagName === 'h1') {
          h1Dropped = true;
          return false;
        }
        return true;
      });
      for (const child of node.children) {
        if (child.type === 'element' && child.tagName === 'a' && typeof child.properties?.href === 'string') {
          child.properties.href = rewriteHref(child.properties.href);
        }
        walk(child);
      }
    };
    walk(tree);
  };
}
