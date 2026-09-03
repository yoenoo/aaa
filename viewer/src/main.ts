import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'

// Default to light; honor a saved preference (only 'dark' overrides the default).
const savedTheme = localStorage.getItem('loupe-viewer-theme')
document.documentElement.dataset.theme = savedTheme === 'dark' ? 'dark' : 'light'

const app = mount(App, {
  target: document.getElementById('app')!,
})

export default app
