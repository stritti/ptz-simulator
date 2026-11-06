// SPDX-FileCopyrightText: 2026 Stephan Strittmatter
// SPDX-License-Identifier: MIT

import { defineConfig } from 'vitepress'

const pagesBase = process.env.BASE_PATH || '/'
if (!/^\/(?!\/)[^?#]*$/.test(pagesBase)) {
  throw new Error('BASE_PATH must start with "/" and be a local path without a query or fragment')
}

// README.md (included as the guide) refers to images and pages by their repository
// path (docs/...) so that they also work on GitHub; on the site the images are served
// from the public directory and the pages from the site root.
function repositoryPathsInReadme(md) {
  md.core.ruler.push('readme-repository-paths', (state) => {
    for (const token of state.tokens) {
      for (const child of token.children || []) {
        const src = child.type === 'image' && child.attrGet('src')
        if (src && src.startsWith('docs/public/')) {
          child.attrSet('src', src.slice('docs/public'.length))
        }
        const href = child.type === 'link_open' && child.attrGet('href')
        const page = href && href.match(/^docs\/([^/#]+)\.md(#.*)?$/)
        if (page) {
          child.attrSet('href', `/${page[1]}${page[2] || ''}`)
        }
      }
    }
  })
}

export default defineConfig({
  base: pagesBase.endsWith('/') ? pagesBase : `${pagesBase}/`,
  lang: 'en-US',
  title: 'ptzsim',
  description: 'A PTZ camera simulator for ONVIF, VISCA and NDI.',
  markdown: { config: repositoryPathsInReadme },
  themeConfig: {
    nav: [
      { text: 'Guide', link: '/guide' },
      { text: 'Camera scene', link: '/scene' },
      { text: 'Protocol reference', link: '/ptz_control_protocols_reference_guide' },
      { text: 'Get started', link: '/guide#running' }
    ],
    sidebar: [
      {
        text: 'Get started',
        items: [
          { text: 'Overview', link: '/guide' },
          { text: 'Supported transports', link: '/guide#supported-transports' },
          { text: 'Run the simulator', link: '/guide#running' },
          { text: 'Keyboard control', link: '/guide#keyboard-control-tui' },
          { text: 'Camera scene', link: '/scene' }
        ]
      },
      {
        text: 'Protocols',
        items: [
          { text: 'Protocol reference', link: '/ptz_control_protocols_reference_guide' },
          { text: 'ONVIF integration', link: '/guide#testing-onvif-clients' },
          { text: 'ONVIF scope', link: '/guide#onvif-scope' },
          { text: 'VISCA clients', link: '/guide#testing-visca-clients' },
          { text: 'VISCA commands', link: '/guide#supported-visca-commands' },
          { text: 'NDI', link: '/guide#ndi' }
        ]
      },
      {
        text: 'Development',
        items: [
          { text: 'Tests', link: '/guide#tests' },
          { text: 'References', link: '/guide#references' }
        ]
      }
    ],
    search: { provider: 'local' },
    socialLinks: [{ icon: 'github', link: 'https://github.com/stritti/ptz-simulator' }],
    footer: { message: 'A PTZ camera simulator for testing camera integrations.' }
  }
})
