using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

// Renders each zone from roughly where the camera client stands, for review
// without starting VRChat.
public static class ChatboxLabPreview
{
    [MenuItem("VRCT-VOX/Render Chatbox Lab Previews")]
    public static void Render()
    {
        if (EditorSceneManager.GetActiveScene().path != ChatboxLabSceneBuilder.ScenePath)
            EditorSceneManager.OpenScene(ChatboxLabSceneBuilder.ScenePath);
        string output = Path.Combine(Path.GetDirectoryName(ChatboxLabBuild.Output), "previews");
        Directory.CreateDirectory(output);
        var camera = new GameObject("PreviewCamera").AddComponent<Camera>();
        camera.fieldOfView = 60f;
        var target = new RenderTexture(960, 540, 24);
        camera.targetTexture = target;
        for (int i = 0; ; i++)
        {
            var zone = GameObject.Find($"Zone{i}");
            if (zone == null) break;
            camera.transform.position = zone.transform.position + new Vector3(0f, 1.6f, -5f);
            camera.transform.LookAt(zone.transform.position + new Vector3(0f, 1.8f, 0f));
            camera.Render();
            RenderTexture.active = target;
            var image = new Texture2D(target.width, target.height, TextureFormat.RGB24, false);
            image.ReadPixels(new Rect(0, 0, target.width, target.height), 0, 0);
            image.Apply();
            File.WriteAllBytes(Path.Combine(output, $"zone{i}.png"), image.EncodeToPNG());
        }
        RenderTexture.active = null;
        Object.DestroyImmediate(camera.gameObject);
        Debug.Log($"Chatbox lab previews written to {output}");
    }
}
