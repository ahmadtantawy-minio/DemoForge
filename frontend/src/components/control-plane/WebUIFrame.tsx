import { proxyUrl } from "../../api/client";

interface Props {
  path: string;
  name: string;
  onClose: () => void;
}

export default function WebUIFrame({ path, name, onClose }: Props) {
  const url = proxyUrl(path);
  return (
    <div className="flex flex-col w-full h-full border border-gray-200 rounded">
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-100 border-b border-gray-200">
        <span className="text-sm font-medium text-gray-700">{name}</span>
        <div className="flex items-center gap-2">
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-blue-600 hover:underline"
          >
            Pop out
          </a>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-800 text-sm"
          >
            ✕
          </button>
        </div>
      </div>
      <iframe
        src={url}
        className="flex-1 w-full border-0"
        title={name}
      />
    </div>
  );
}
