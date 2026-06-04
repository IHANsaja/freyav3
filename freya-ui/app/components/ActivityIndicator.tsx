"use client";

interface ActivityIndicatorProps {
  active: boolean;
}

export default function ActivityIndicator({ active }: ActivityIndicatorProps) {
  if (!active) {
    // Show static subtle indicator
    return (
      <div className="flex items-center gap-1 h-4 px-1" title="System idle">
        <span className="w-[1.5px] h-3 bg-muted-blood/40"></span>
        <span className="w-[1.5px] h-2 bg-muted-blood/40"></span>
        <span className="w-[1.5px] h-4 bg-muted-blood/40"></span>
        <span className="w-[1.5px] h-1.5 bg-muted-blood/40"></span>
        <span className="w-[1.5px] h-2.5 bg-muted-blood/40"></span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1 h-4 px-1" title="System processing data stream">
      <span className="w-[1.5px] h-3 bg-primary-container animate-pulse-line-1 origin-center"></span>
      <span className="w-[1.5px] h-2 bg-primary-container animate-pulse-line-2 origin-center"></span>
      <span className="w-[1.5px] h-4 bg-primary-container animate-pulse-line-3 origin-center"></span>
      <span className="w-[1.5px] h-1.5 bg-primary-container animate-pulse-line-4 origin-center"></span>
      <span className="w-[1.5px] h-2.5 bg-primary-container animate-pulse-line-5 origin-center"></span>
    </div>
  );
}
