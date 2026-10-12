import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import {fileURLToPath,URL} from 'node:url';
export default defineConfig({plugins:[react(),tailwindcss()],resolve:{alias:{'@':fileURLToPath(new URL('./src',import.meta.url))},dedupe:['react','react-dom']},build:{rollupOptions:{output:{manualChunks(id){if(/node_modules\/(react|react-dom|scheduler)\//.test(id))return 'react-vendor';if(id.includes('node_modules/@radix-ui/'))return 'radix-vendor'}}}}});
