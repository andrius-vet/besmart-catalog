window.CMS_MANUAL_INIT = false;
window.CMS_CONFIG = {
  backend: { name: "git-gateway", branch: "main" },
  load_config_file: false,
  media_folder: "static/img",
  public_folder: "/static/img",
  publish_mode: "simple",
  collections: [
    {
      name: "playlists",
      label: "Playlists",
      label_singular: "Playlist",
      folder: "content/playlists",
      create: true,
      slug: "{{slug}}",
      extension: "json",
      format: "json",
      fields: [
        { name: "id", label: "ID", widget: "string" },
        { name: "title", label: "Title", widget: "string" },
        { name: "url", label: "YouTube Playlist URL", widget: "string" },
        { name: "thumbnail", label: "Thumbnail URL", widget: "string", required: false },
        { name: "categories", label: "Categories", widget: "list", default: [] },
        { name: "langCode", label: "Language (optional, e.g. en, lt)", widget: "string", required: false }
      ]
    },
    {
      name: "videos",
      label: "Single YouTube videos",
      folder: "content/videos",
      create: true,
      slug: "{{slug}}",
      extension: "json",
      format: "json",
      fields: [
        { name: "id", label: "ID", widget: "string" },
        { name: "title", label: "Title", widget: "string" },
        { name: "url", label: "YouTube URL", widget: "string" },
        { name: "thumbnail", label: "Thumbnail URL", widget: "string", required: false },
        { name: "categories", label: "Categories", widget: "list", default: [] },
        { name: "langCode", label: "Language (optional, e.g. en, lt)", widget: "string", required: false }
      ]
    },
    {
      name: "categories",
      label: "Categories (taxonomy)",
      files: [
        {
          name: "categories",
          label: "Categories",
          file: "content/categories.json",
          fields: [{ name: "items", label: "Items", widget: "list", fields: [{name:"id",label:"ID"}, {name:"label",label:"Label"}]}]
        }
      ]
    }
  ]
};
