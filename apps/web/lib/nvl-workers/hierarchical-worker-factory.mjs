export const createHierarchicalLayoutWorker = () =>
  new SharedWorker(
    "/workers/nvl/hierarchical-layout/HierarchicalLayout.worker.js",
    {
      type: "module",
      name: "HierarchicalLayout",
    },
  );
