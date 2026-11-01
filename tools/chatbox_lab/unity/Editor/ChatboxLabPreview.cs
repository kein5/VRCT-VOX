using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

// Renders each zone from two places the camera client may stand, for review
// without starting VRChat.
public static class ChatboxLabPreview
{
    static readonly Vector3[] Views = { new Vector3(0f, 1.6f, -5f), new Vector3(4f, 1.6f, 4.5f) };

    [MenuItem("VRCT-VOX/Render Chatbox Lab Previews")]
    public static void Render()
    {
        if (EditorSceneManager.GetActiveScene().path != ChatboxLabSceneBuilder.ScenePath)
            EditorSceneManager.OpenScene(ChatboxLabSceneBuilder.ScenePath);
        string output = Path.Combine(Path.GetDirectoryName(ChatboxLabBuild.Output), "previews");
        Directory.CreateDirectory(output);
        for (int i = 0; ; i++)
        {
            var zone = GameObject.Find($"Zone{i}");
            if (zone == null) break;
            for (int v = 0; v < Views.Length; v++)
                Save(Shot(zone.transform.position + Views[v], zone.transform.position + new Vector3(0f, 1.8f, 0f), 1280, 720),
                    Path.Combine(output, $"zone{i}_{v}.png"));
        }
        Debug.Log($"Chatbox lab previews written to {output}");
    }

    public static Texture2D Shot(Vector3 from, Vector3 at, int width, int height)
    {
        var camera = new GameObject("PreviewCamera").AddComponent<Camera>();
        camera.fieldOfView = 60f;
        camera.farClipPlane = 200f;
        camera.allowHDR = true;
        ChatboxLabSceneBuilder.AddPostLayer(camera.gameObject);
        var target = new RenderTexture(width, height, 24);
        camera.targetTexture = target;
        camera.transform.position = from;
        camera.transform.LookAt(at);
        camera.Render();
        RenderTexture.active = target;
        var image = new Texture2D(width, height, TextureFormat.RGB24, false);
        image.ReadPixels(new Rect(0, 0, width, height), 0, 0);
        image.Apply();
        RenderTexture.active = null;
        camera.targetTexture = null;
        Object.DestroyImmediate(camera.gameObject);
        Object.DestroyImmediate(target);
        return image;
    }

    public static void Save(Texture2D image, string path)
    {
        File.WriteAllBytes(path, image.EncodeToPNG());
        Object.DestroyImmediate(image);
    }
}
