// SPDX-FileCopyrightText: 2026 Stephan Strittmatter
// SPDX-License-Identifier: MIT

import { defineConfig } from 'vitepress'

const pagesBase = process.env.BASE_PATH || '/'
if (!/^\/(?!\/)[^?#]*$/.test(pagesBase)) {
  throw new Error('BASE_PATH must start with "/" and be a local path without a query or fragment')
}

export default defineConfig({
  base: pagesBase.endsWith('/') ? pagesBase : `${pagesBase}/`,
  lang: 'en-US',
  title: 'ptzsim',
  description: 'A PTZ camera simulator for ONVIF, VISCA and NDI.',
  themeConfig: {
    nav: [
      { text: 'Guide', link: '/guide' },
      { text: 'Get started', link: '/guide#running' }
    ],
    sidebar: [
      {
        text: 'Get started',
        items: [
          { text: 'Overview', link: '/guide' },
          { text: 'Supported transports', link: '/guide#supported-transports' },
          { text: 'Run the simulator', link: '/guide#running' },
          { text: 'Keyboard control', link: '/guide#keyboard-control-tui' }
        ]
      },
      {
        text: 'Protocols',
        items: [
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
