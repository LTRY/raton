import assert from 'node:assert/strict';
import { test } from 'node:test';
import rehypeSpec, { rewriteHref } from './rehype-spec.mjs';

test('rewrites links to sibling specs', () => {
  assert.equal(rewriteHref('11-interface-html.md'), '/11-interface-html/');
  assert.equal(rewriteHref('11-interface-html.md#accueil'), '/11-interface-html/#accueil');
  assert.equal(rewriteHref('README.md'), '/');
});

test('leaves other links alone', () => {
  for (const href of ['#section', 'https://example.com/a.md', '/already/', '../x.md', 'mailto:a@b.c']) {
    assert.equal(rewriteHref(href), href);
  }
});

test('drops only the first h1 and rewrites nested links', () => {
  const link = { type: 'element', tagName: 'a', properties: { href: '00-vision.md' }, children: [] };
  const tree = {
    type: 'root',
    children: [
      { type: 'element', tagName: 'h1', properties: {}, children: [] },
      { type: 'element', tagName: 'p', properties: {}, children: [link] },
      { type: 'element', tagName: 'h1', properties: {}, children: [] },
    ],
  };
  rehypeSpec()(tree);
  assert.deepEqual(tree.children.map((c) => c.tagName), ['p', 'h1']);
  assert.equal(link.properties.href, '/00-vision/');
});
