using System;
using System.IO;
using UnityEditor;
using UnityEngine;

// Lets tools/chatbox_lab/unity_remote.py run the lab's own menu actions in an
// editor that is already open (and signed in to the SDK), since batch mode
// cannot open the same project. It reads one command at a time from
// ~/.cache/vrct-vox-chatbox-lab/remote/command and writes result.json; only
// the commands below exist.
[InitializeOnLoad]
public static class ChatboxLabRemote
{
    static string Folder => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".cache", "vrct-vox-chatbox-lab", "remote");
    static double next;
    static bool busy;

    [Serializable]
    class Result
    {
        public string command;
        public bool ok;
        public string message;
        public string finished;
    }

    static ChatboxLabRemote()
    {
        EditorApplication.update += Poll;
    }

    static async void Poll()
    {
        if (busy || EditorApplication.timeSinceStartup < next || EditorApplication.isCompiling || EditorApplication.isUpdating) return;
        next = EditorApplication.timeSinceStartup + 1.0;
        string path = Path.Combine(Folder, "command");
        if (!File.Exists(path)) return;
        string command = File.ReadAllText(path).Trim();
        File.Delete(path);
        busy = true;
        var result = new Result { command = command, ok = true };
        try
        {
            switch (command)
            {
                case "refresh": AssetDatabase.Refresh(); result.message = "refreshed"; break;
                case "build-scene": ChatboxLabSceneBuilder.BuildScene(); result.message = "scene built"; break;
                case "previews": ChatboxLabPreview.Render(); result.message = "previews written"; break;
                case "build-world": result.message = await ChatboxLabBuild.Build(); break;
                case "upload": result.message = await ChatboxLabBuild.Upload(); break;
                case "save-world-id": result.message = ChatboxLabBuild.SaveWorldId(); break;
                default: result.ok = false; result.message = $"unknown command {command}"; break;
            }
        }
        catch (Exception error)
        {
            result.ok = false;
            result.message = error.ToString();
        }
        finally
        {
            busy = false;
        }
        result.finished = DateTime.Now.ToString("o");
        File.WriteAllText(Path.Combine(Folder, "result.json"), JsonUtility.ToJson(result));
    }
}
