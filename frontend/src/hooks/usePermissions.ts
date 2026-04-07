import { useEffect, useState } from "react";
import { fetchMe } from "../api/client";

interface Permissions {
  manual_demo_creation: boolean;
  template_publish: boolean;
  template_fork: boolean;
  max_concurrent_demos: number;
}

const DEFAULT_PERMISSIONS: Permissions = {
  manual_demo_creation: true,
  template_publish: true,
  template_fork: true,
  max_concurrent_demos: 5,
};

export function usePermissions() {
  const [permissions, setPermissions] = useState<Permissions>(DEFAULT_PERMISSIONS);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetchMe()
      .then((me) => {
        if (me.ok && me.permissions) {
          setPermissions({ ...DEFAULT_PERMISSIONS, ...me.permissions } as Permissions);
        }
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  return { permissions, loaded };
}
