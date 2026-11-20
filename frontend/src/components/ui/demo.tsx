"use client";

import ShaderAuroraVeil from "./shader-aurora-veil";

export default function ShaderAuroraVeilDemo() {
  return (
    <div className="relative h-screen w-full">
      <ShaderAuroraVeil
        preset="aurora-veil"
        tone="dark"
        className="absolute inset-0 h-full w-full"
      />
    </div>
  );
}

