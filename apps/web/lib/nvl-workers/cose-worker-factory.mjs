export const createCoseBilkentLayoutWorker = () =>
  new SharedWorker(
    "/workers/nvl/cosebilkent-layout/CoseBilkentLayout.worker.js",
    {
      type: "module",
      name: "CoseBilkentLayout",
    },
  );
