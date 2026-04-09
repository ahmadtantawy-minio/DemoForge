interface Props {
  onClick: () => void;
}

export default function AddPoolButton({ onClick }: Props) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="w-full mt-2 text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
      style={{
        border: "1px dashed rgba(212,212,216,0.3)",
        borderRadius: 8,
        padding: 5,
        background: "transparent",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "rgba(212,212,216,0.5)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "rgba(212,212,216,0.3)";
      }}
    >
      + Add server pool
    </button>
  );
}
