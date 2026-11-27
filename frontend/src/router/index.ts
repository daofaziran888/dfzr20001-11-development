import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'
import PipelineDashboard from '@/views/PipelineDashboard.vue'
import ReinspectionView from '@/views/ReinspectionView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/pipeline', name: 'pipeline', component: PipelineDashboard },
    { path: '/reinspection', name: 'reinspection', component: ReinspectionView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router