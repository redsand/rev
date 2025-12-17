from typing import Dict, Any, List, Optional
import os

def list_files(directory: str = ".", filter_ext: Optional[str] = None, sort_by: str = "name") -> Dict[str, Any]:
    """List files in a directory with optional filtering and sorting.

    Args:
        directory: Directory path to list files from (default: current directory)
        filter_ext: File extension to filter by (e.g., '.py', '.md') (default: None)
        sort_by: Sort criteria - "name", "size", or "modified" (default: "name")

    Returns:
        Dictionary containing file listing results with file details.

    Raises:
        ValueError: If directory doesn't exist or sort_by is invalid
        OSError: If there are permission issues accessing the directory
    """
    try:
        if not os.path.exists(directory):
            raise ValueError(f"Directory '{directory}' does not exist")
        
        if not os.path.isdir(directory):
            raise ValueError(f"Path '{directory}' is not a directory")
        
        # Get all files in directory
        files = []
        for entry in os.scandir(directory):
            if entry.is_file():
                file_info = {
                    "name": entry.name,
                    "path": entry.path,
                    "size": entry.stat().st_size,
                    "modified": entry.stat().st_mtime
                }
                files.append(file_info)
        
        # Apply filtering if specified
        if filter_ext:
            files = [f for f in files if f["name"].endswith(filter_ext)]
        
        # Apply sorting
        if sort_by == "name":
            files.sort(key=lambda x: x["name"])
        elif sort_by == "size":
            files.sort(key=lambda x: x["size"])
        elif sort_by == "modified":
            files.sort(key=lambda x: x["modified"])
        else:
            raise ValueError("sort_by must be one of: 'name', 'size', 'modified'")
        
        return {
            "status": "success",
            "directory": directory,
            "filter": filter_ext,
            "sort_by": sort_by,
            "file_count": len(files),
            "files": files
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }