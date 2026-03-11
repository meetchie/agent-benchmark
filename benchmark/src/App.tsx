import tasksData from "../tasks.yaml";
export default function App() {
  return (
    <div className="min-h-screen bg-[#f0f4ff] p-8">
      <p className="text-[#3c49ad] font-bold">
        Categories: {tasksData.categories.length}
      </p>
    </div>
  );
}
