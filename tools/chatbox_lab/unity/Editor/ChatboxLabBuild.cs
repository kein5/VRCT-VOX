using System;
using System.IO;
using System.Threading.Tasks;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using VRC.SDK3.Editor;
using VRC.SDKBase.Editor;

// Builds the chatbox lab world bundle with the SDK and copies it to a fixed
// place, where tools/chatbox_lab/launch_clients.py starts the test clients
// through Proton. The SDK's own Build & Test cannot start VRChat on Linux.
public static class ChatboxLabBuild
{
    public static string Output => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        ".cache", "vrct-vox-chatbox-lab", "world.vrcw");

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

    public static async Task<string> Build()
    {
        if (EditorSceneManager.GetActiveScene().path != ChatboxLabSceneBuilder.ScenePath)
            EditorSceneManager.OpenScene(ChatboxLabSceneBuilder.ScenePath);
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
                string bundle = await builder.Build();
                Directory.CreateDirectory(Path.GetDirectoryName(Output));
                File.Copy(bundle, Output, true);
                return Output;
            }
            catch (BuilderException error) when (error.Message.Contains("Open the SDK panel"))
            {
                last = error;
            }
        }
        throw new InvalidOperationException(builder == null
            ? "Sign in under VRChat SDK > Show Control Panel, then build again."
            : "The SDK panel did not pick up the scene; open its Builder tab and build again.", last);
    }
}
