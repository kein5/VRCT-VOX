using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using VRC.Core;
using VRC.SDK3.Editor;
using VRC.SDKBase.Editor;
using VRC.SDKBase.Editor.Api;

// Builds the chatbox lab world bundle with the SDK and copies it to a fixed
// place, where tools/chatbox_lab/launch_clients.py starts the test clients
// through Proton. The SDK's own Build & Test cannot start VRChat on Linux.
//
// Upload publishes it as a private world, so the lab's own accounts can meet in
// an invite-only instance on VRChat's servers. The scene is rebuilt from code,
// so the world id is kept in world-id next to the bundle and put back each time.
// Create the world once from the SDK panel (its id check races a scripted first
// upload) and run SaveWorldId; later uploads can run from here.
public static class ChatboxLabBuild
{
    static string Cache => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".cache", "vrct-vox-chatbox-lab");
    public static string Output => Path.Combine(Cache, "world.vrcw");
    static string WorldIdFile => Path.Combine(Cache, "world-id");

    [MenuItem("VRCT-VOX/Build Chatbox Lab World")]
    public static async void BuildMenu()
    {
        try
        {
            Debug.Log($"Chatbox lab world written to {await Build()}");
        }
        catch (Exception error)
        {
            Debug.LogError($"Chatbox lab build failed: {error}");
        }
    }

    [MenuItem("VRCT-VOX/Upload Chatbox Lab World (private)")]
    public static async void UploadMenu()
    {
        try
        {
            Debug.Log($"Chatbox lab world uploaded as {await Upload()}");
        }
        catch (Exception error)
        {
            Debug.LogError($"Chatbox lab upload failed: {error}");
        }
    }

    public static async Task<string> Build()
    {
        string bundle = await WhenPanelReady(builder => builder.Build());
        Directory.CreateDirectory(Cache);
        File.Copy(bundle, Output, true);
        return Output;
    }

    public static async Task<string> Upload()
    {
        string id = File.Exists(WorldIdFile) ? File.ReadAllText(WorldIdFile).Trim() : "";
        string thumbnail = null;
        VRCWorld world;
        if (id.Length > 0)
        {
            // An update keeps the name, description and image set on the site or in the panel.
            world = await VRCApi.GetWorld(id, true);
        }
        else
        {
            thumbnail = Path.Combine(Cache, "thumbnail.png");
            var zone = GameObject.Find("Zone9") ?? GameObject.Find("Zone0");
            ChatboxLabPreview.Save(ChatboxLabPreview.Shot(zone.transform.position + new Vector3(0f, 1.8f, -6f),
                zone.transform.position + new Vector3(0f, 1.8f, 0f), 1200, 900), thumbnail);
            world = new VRCWorld
            {
                Name = "VRCT-VOX Chatbox Lab",
                Description = "Private test world for collecting VRChat chatbox screenshots for VRCT-VOX. Not for public use.",
                Capacity = 4,
                RecommendedCapacity = 2,
                Tags = new List<string>(),
            };
        }
        await WhenPanelReady(async builder => { await builder.BuildAndUpload(world, thumbnailPath: thumbnail); return true; });
        id = Pipeline().blueprintId;
        File.WriteAllText(WorldIdFile, id);
        EditorSceneManager.SaveScene(EditorSceneManager.GetActiveScene());
        return id;
    }

    // After the first upload from the SDK panel: keep the id it gave the world.
    public static string SaveWorldId()
    {
        string id = Pipeline()?.blueprintId;
        if (string.IsNullOrEmpty(id)) throw new InvalidOperationException("The scene has no world id yet; upload it first.");
        File.WriteAllText(WorldIdFile, id);
        EditorSceneManager.SaveScene(EditorSceneManager.GetActiveScene());
        return id;
    }

    // Puts the saved world id back after the scene was rebuilt.
    public static void RestoreWorldId()
    {
        if (!File.Exists(WorldIdFile)) return;
        string id = File.ReadAllText(WorldIdFile).Trim();
        var pipeline = Pipeline();
        if (string.IsNullOrEmpty(id) || pipeline == null || pipeline.blueprintId == id) return;
        pipeline.blueprintId = id;
        EditorUtility.SetDirty(pipeline);
        EditorSceneManager.MarkSceneDirty(pipeline.gameObject.scene);
        EditorSceneManager.SaveScene(pipeline.gameObject.scene);
    }

    static PipelineManager Pipeline() => UnityEngine.Object.FindObjectOfType<PipelineManager>();

    static async Task<T> WhenPanelReady<T>(Func<IVRCSdkWorldBuilderApi, Task<T>> action)
    {
        if (EditorSceneManager.GetActiveScene().path != ChatboxLabSceneBuilder.ScenePath)
            EditorSceneManager.OpenScene(ChatboxLabSceneBuilder.ScenePath);
        RestoreWorldId();
        // The panel finds the scene's descriptor only while it is open and has
        // redrawn its Builder tab, so open it and wait for that first.
        var panel = EditorWindow.GetWindow<VRCSdkControlPanel>();
        panel.Show();
        panel.Focus();
        IVRCSdkWorldBuilderApi builder = null;
        Exception last = null;
        for (int attempt = 0; attempt < 40; attempt++)
        {
            panel.Repaint();
            await Task.Delay(500);
            if (!VRCSdkControlPanel.TryGetBuilder(out builder)) continue;
            try
            {
                return await action(builder);
            }
            catch (BuilderException error) when (error.Message.Contains("Open the SDK panel"))
            {
                last = error;
            }
        }
        throw new InvalidOperationException(builder == null
            ? "Sign in under VRChat SDK > Show Control Panel, then try again."
            : "The SDK panel did not pick up the scene; open its Builder tab and try again.", last);
    }
}
